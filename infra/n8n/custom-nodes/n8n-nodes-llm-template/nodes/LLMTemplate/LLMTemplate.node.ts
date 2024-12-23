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
    private static modelCache: Record<string, any> = {};

    // Add static methods to handle the cache
    public static getFromCache(key: string): any {
        return this.modelCache[key];
    }

    public static setInCache(key: string, value: any): void {
        this.modelCache[key] = value;
    }

    public static hasInCache(key: string): boolean {
        return key in this.modelCache;
    }

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
                displayName: 'Field Mappings',
                name: 'fieldMappings',
                type: 'fixedCollection',
                typeOptions: {
                    multipleValues: true,
                },
                default: {},
                options: [
                    {
                        name: 'mapping',
                        displayName: 'Mapping',
                        values: [
                            {
                                displayName: 'Field Name',
                                name: 'field',
                                type: 'string',
                                default: '',
                                description: 'Name of the field to match in input',
                            },
                            {
                                displayName: 'Value',
                                name: 'value',
                                type: 'string',
                                default: '',
                                description: 'Expression or value to use if field matches',
                                noDataExpression: false,
                            },
                        ],
                    },
                ],
            },
            {
                displayName: 'Template',
                name: 'template',
                type: 'string',
                typeOptions: {
                    rows: 10,
                },
                default: '',
                description: 'Template for LLM processing',
                required: true,
                noDataExpression: true,
            },
        ],
    };

    methods = {
        loadOptions: {
            async getInputModels(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
                return loadModels.call(this, 'input');
            },
            async getOutputModels(this: ILoadOptionsFunctions): Promise<INodePropertyOptions[]> {
                return loadModels.call(this, 'output');
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
            const fieldMappings = (this.getNodeParameter('fieldMappings', i) as { mapping: Array<{ field: string; value: string }> }).mapping || [];

            const variables: Record<string, any> = { ...items[i].json };

            let outputModelSchema;
            try {
                const models = await ensureModelsLoaded.call(this, apiEndpoint);
                outputModelSchema = models[outputModel]?.schema;
            } catch (error) {
                console.warn('Failed to load model schema:', error);
                outputModelSchema = null;
            }

            // Handle field mappings with special case for empty objects
            fieldMappings.forEach(mapping => {
                if (!mapping || typeof mapping !== 'object') return;

                const { field, value } = mapping;
                if (!field) return;

                try {
                    // Safely handle the empty object case
                    if (typeof value === 'string' && value.trim() === '{}') {
                        variables[field] = {};
                        return;
                    }

                    // Handle undefined/null values
                    if (value === undefined || value === null) {
                        variables[field] = null;
                        return;
                    }

                    // Try to evaluate the expression
                    try {
                        variables[field] = this.evaluateExpression(value, i);
                    } catch {
                        // If evaluation fails, use the raw value
                        variables[field] = value;
                    }
                } catch (error) {
                    console.warn(`Error processing field mapping for ${field}:`, error);
                    variables[field] = null;
                }
            });

            try {
                console.log('Request variables:', JSON.stringify(variables, null, 2));
                const response = await this.helpers.request({
                    method: 'POST',
                    url: `${apiEndpoint}/api/v1/process-template`,
                    body: {
                        template,
                        input_model: inputModel,
                        output_model: outputModel,
                        variables,
                    },
                    json: true,
                });

                // Handle empty response
                if (!response) {
                    const emptyResponse = outputModelSchema ?
                        LLMTemplate.createEmptyModelInstance(outputModelSchema) :
                        {};
                    returnData.push({ json: emptyResponse });
                    continue;
                }

                returnData.push({ json: response });
            } catch (error) {
                console.error('Request error:', error);
                if (error instanceof NodeApiError || error instanceof NodeOperationError) {
                    if (this.continueOnFail()) {
                        returnData.push({ json: { error: error.message } });
                        continue;
                    }
                    throw error;
                }
                if (this.continueOnFail()) {
                    const emptyResponse = outputModelSchema ?
                        LLMTemplate.createEmptyModelInstance(outputModelSchema) :
                        {};
                    returnData.push({ json: emptyResponse });
                    continue;
                }
                throw error;
            }
        }

        return [returnData];
    }

    // Make this static so it can be called from instance methods
    protected static createEmptyModelInstance(schema: any): Record<string, any> {
        if (!schema || !schema.properties) return {};

        const result: Record<string, any> = {};

        // First ensure all required fields exist
        if (schema.required) {
            schema.required.forEach((field: string) => {
                const prop = schema.properties[field];
                result[field] = this.getDefaultValueForType(prop);
            });
        }

        // Then handle all other properties
        for (const [key, prop] of Object.entries<any>(schema.properties)) {
            if (!(key in result)) {  // Skip if already handled as required
                result[key] = this.getDefaultValueForType(prop);
            }
        }

        return result;
    }
    private static getDefaultValueForType(prop: any): any {
        if (!prop) return null;

        // First check if there's an explicit default
        if ('default' in prop) return prop.default;

        // Handle based on type
        switch (prop.type) {
            case 'string':
                return '';
            case 'number':
            case 'integer':
                return 0;
            case 'boolean':
                return false;
            case 'array':
                return [];
            case 'object':
                if (prop.properties) {
                    return this.createEmptyModelInstance(prop);
                }
                return {};
            case 'null':
                return null;
            default:
                return null;
        }
    }
}


async function loadModels(this: ILoadOptionsFunctions, type: string): Promise<INodePropertyOptions[]> {
    try {
        const apiEndpoint = this.getNodeParameter('apiEndpoint') as string;
        if (!apiEndpoint) return [{ name: 'No API Endpoint Set', value: '' }];

        const models = await ensureModelsLoaded.call(this, apiEndpoint);

        const options = Object.entries(models)
            .filter(([_, model]: [string, any]) => model.module_type === type)
            .map(([name, model]: [string, any]) => ({
                name,
                value: name,
                description: generateModelDescription(model),
            }));

        return options.length === 0 ?
            [{ name: `No ${type === 'input' ? 'Input' : 'Output'} Models Available`, value: '' }] :
            options;
    } catch (error: any) {
        return [{ name: `Error: ${error?.message || 'Failed to load models'}`, value: '' }];
    }
}

async function ensureModelsLoaded(this: ILoadOptionsFunctions | IExecuteFunctions, apiEndpoint: string): Promise<Record<string, any>> {
    const cacheKey = apiEndpoint;

    if (!LLMTemplate.hasInCache(cacheKey)) {
        try {
            const response = await this.helpers.request({
                method: 'GET',
                url: `${apiEndpoint}/api/v1/models`,
                json: true,
            });

            if (!response) {
                throw new Error('No models returned from API');
            }

            LLMTemplate.setInCache(cacheKey, response);
        } catch (error) {
            console.error('Failed to load models:', error);
            throw error;
        }
    }

    return LLMTemplate.getFromCache(cacheKey);
}
function generateModelDescription(model: any): string {
    const schema = model.schema;
    let description = '';

    if (!schema || !schema.properties) return description;

    Object.entries(schema.properties).forEach(([fieldName, field]: [string, any]) => {
        description += `${fieldName} (${field.type})\n`;
        const desc = field.description || field.title;
        if (desc) {
            const wrappedDesc = desc.match(/.{1,80}(\s+|$)/g)?.join('\n --- \n   ') || desc;
            description += `    ${wrappedDesc}\n`;
        }
        const constraints = [];
        if (field.minimum !== undefined) constraints.push(`minimum: ${field.minimum}`);
        if (field.maximum !== undefined) constraints.push(`maximum: ${field.maximum}`);
        if (constraints.length > 0) description += `    Constraints: ${constraints.join(', ')}\n`;
        description += '\n';
    });
    if (schema.required?.length > 0) {
        description += '\nRequired fields:\n';
        schema.required.forEach((field: string) => {
            description += `  • ${field}\n`;
        });
    }
    return description.trim();
}
