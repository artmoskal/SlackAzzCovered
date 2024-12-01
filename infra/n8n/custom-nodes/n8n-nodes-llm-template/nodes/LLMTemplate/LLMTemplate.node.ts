import {
    IExecuteFunctions,
    INodeExecutionData,
    INodeType,
    INodeTypeDescription,
    ILoadOptionsFunctions,
    INodePropertyOptions,
    NodeApiError,
    NodeOperationError,
} from 'n8n-workflow';

export class LLMTemplate implements INodeType {
    description: INodeTypeDescription = {
        displayName: 'Dynamic LLM Processor V1',
        name: 'dynamicLLMProcessor',
        group: ['transform'],
        version: 1,
        description: 'Process text using LLM with dynamic model selection',
        defaults: {
            name: 'LLM Processor',
        },
        inputs: ['main'],
        outputs: ['main'],
        properties: [
            {
                displayName: 'API Endpoint',
                name: 'apiEndpoint',
                type: 'string',
                default: '={{ $env.API_HOST_URL }}',
                required: true,
                hint: 'Default is set from API_HOST_URL environment variable',
                noDataExpression: false,
            },
            {
                displayName: 'Input Model',
                name: 'inputModel',
                type: 'options',
                typeOptions: {
                    loadOptionsMethod: 'getInputModels',
                },
                required: true,
                default: '',
                noDataExpression: true,
            },
            {
                displayName: 'Output Model',
                name: 'outputModel',
                type: 'options',
                typeOptions: {
                    loadOptionsMethod: 'getOutputModels',
                },
                required: true,
                default: '',
                noDataExpression: true,
            },
            {
                displayName: 'Template',
                name: 'template',
                type: 'string',
                typeOptions: {
                    rows: 10,
                },
                default: '',
                description: 'Jinja2 template for LLM processing',
                required: true,
                noDataExpression: true,
            },
        ],
    };

    methods = {
        loadOptions: {
            async getInputModels(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
                try {
                    const apiEndpoint = this.getNodeParameter('apiEndpoint') as string;
                    console.log('Loading input models from:', apiEndpoint);

                    if (!apiEndpoint) {
                        return [{ name: 'No API Endpoint Set', value: '' }];
                    }

                    const response = await this.helpers.request({
                        method: 'GET',
                        url: `${apiEndpoint}/api/v1/models`,
                        json: true,
                    });

                    console.log('API Response for input models:', response);

                    if (!response) {
                        return [{ name: 'No Models Found', value: '' }];
                    }

                    const options = Object.entries(response)
                        .filter(([_, model]: [string, any]) => model.module_type === 'input')
                        .map(([name, model]: [string, any]) => ({
                            name,
                            value: name,
                            description: generateModelDescription(model),
                        }));

                    if (options.length === 0) {
                        return [{ name: 'No Input Models Available', value: '' }];
                    }

                    return options;
                } catch (error: any) {
                    console.error('Error loading input models:', error);
                    return [{
                        name: `Error: ${error?.message || 'Failed to load models'}`,
                        value: ''
                    }];
                }
            },

            async getOutputModels(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
                try {
                    const apiEndpoint = this.getNodeParameter('apiEndpoint') as string;
                    console.log('Loading output models from:', apiEndpoint);

                    if (!apiEndpoint) {
                        return [{ name: 'No API Endpoint Set', value: '' }];
                    }

                    const response = await this.helpers.request({
                        method: 'GET',
                        url: `${apiEndpoint}/api/v1/models`,
                        json: true,
                    });

                    console.log('API Response for output models:', response);

                    if (!response) {
                        return [{ name: 'No Models Found', value: '' }];
                    }

                    const options = Object.entries(response)
                        .filter(([_, model]: [string, any]) => model.module_type === 'output')
                        .map(([name, model]: [string, any]) => ({
                            name,
                            value: name,
                            description: generateModelDescription(model),
                        }));

                    if (options.length === 0) {
                        return [{ name: 'No Output Models Available', value: '' }];
                    }

                    return options;
                } catch (error: any) {
                    console.error('Error loading output models:', error);
                    return [{
                        name: `Error: ${error?.message || 'Failed to load models'}`,
                        value: ''
                    }];
                }
            },
        },
    };

    async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
        const items = this.getInputData();
        const returnData: INodeExecutionData[] = [];

        for (let i = 0; i < items.length; i++) {
            const apiEndpoint = this.getNodeParameter('apiEndpoint', i) as string;
            console.log('Execute - Using API endpoint:', apiEndpoint);

            if (!apiEndpoint) {
                throw new Error('API endpoint is not set');
            }

            const inputModel = this.getNodeParameter('inputModel', i) as string;
            const outputModel = this.getNodeParameter('outputModel', i) as string;
            const template = this.getNodeParameter('template', i) as string;

            try {
                console.log('Making request with:', {
                    inputModel,
                    outputModel,
                    template,
                    variables: items[i].json
                });

                const response = await this.helpers.request({
                    method: 'POST',
                    url: `${apiEndpoint}/api/v1/process-template`,
                    body: {
                        template,
                        input_model: inputModel,
                        output_model: outputModel,
                        variables: items[i].json,
                    },
                    json: true,
                });

                console.log('Execute response:', response);
                returnData.push({ json: response });
            } catch (error) {
                console.error('Execute error:', error);

                if (error instanceof NodeApiError || error instanceof NodeOperationError) {
                    if (this.continueOnFail()) {
                        returnData.push({ json: { error: error.message } });
                        continue;
                    }
                    throw error;
                }

                if (this.continueOnFail()) {
                    returnData.push({ json: { error: 'Unknown error occurred' } });
                    continue;
                }
                throw error;
            }
        }

        return [returnData];
    }
}

function generateModelDescription(model: any): string {
    const schema = model.schema;
    let description = '';

    Object.entries(schema.properties).forEach(([fieldName, field]: [string, any]) => {
        // Field name and type
        description += `${fieldName} (${field.type})\n`;

        // Description with proper indentation
        const desc = field.description || field.title;
        const wrappedDesc = desc.match(/.{1,80}(\s+|$)/g)?.join('\n --- \n   ') || desc;
        description += `    ${wrappedDesc}\n`;

        // Constraints
        const constraints = [];
        if (field.minimum !== undefined) constraints.push(`minimum: ${field.minimum}`);
        if (field.maximum !== undefined) constraints.push(`maximum: ${field.maximum}`);

        if (constraints.length > 0) {
            description += `    Constraints: ${constraints.join(', ')}\n`;
        }

        description += '\n';
    });

    // Required fields section
    if (schema.required?.length > 0) {
        description += '\nRequired fields:\n';
        schema.required.forEach((field: string) => {
            description += `  • ${field}\n`;
        });
    }

    return description.trim();
}